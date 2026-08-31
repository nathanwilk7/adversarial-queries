SET join_collapse_limit = 1;
SELECT count(*)
FROM (aka_name CROSS JOIN ((((cast_info CROSS JOIN char_name) CROSS JOIN name) CROSS JOIN link_type) CROSS JOIN movie_link)) CROSS JOIN title
WHERE char_name.name_pcode_nf = 'O3165'
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.person_role_id = char_name.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id;
