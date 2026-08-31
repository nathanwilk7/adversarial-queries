SET join_collapse_limit = 1;
SELECT count(*)
FROM (((cast_info CROSS JOIN (title CROSS JOIN link_type)) CROSS JOIN movie_link) CROSS JOIN movie_info) CROSS JOIN char_name
WHERE char_name.surname_pcode = ''
  AND cast_info.movie_id = title.id
  AND cast_info.person_role_id = char_name.id
  AND movie_info.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id;
