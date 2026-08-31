SET join_collapse_limit = 1;
SELECT count(*)
FROM (((((title CROSS JOIN cast_info) CROSS JOIN name) CROSS JOIN char_name) CROSS JOIN movie_link) CROSS JOIN aka_name) CROSS JOIN link_type
WHERE char_name.surname_pcode = ''
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.person_role_id = char_name.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id;
