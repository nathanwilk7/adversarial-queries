SELECT count(*)
FROM aka_title, cast_info, complete_cast, info_type, keyword, link_type, movie_keyword, movie_link, name, person_info, role_type, title
WHERE info_type.info = 'LD production country'
  AND name.imdb_index = 'XC'
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.role_id = role_type.id
  AND complete_cast.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id;
